## ADDED Requirements

### Requirement: Source implementation does not promote deferred predecessor acceptance
During the explicitly ordered continuous migration, C5 source implementation MAY begin from a `git_lfs_work_product_source_only_dependency_gate@1` before final C2--C4 acceptance receipts are issued. The gate MUST bind the immutable C1 acceptance receipt, current C2--C4 source/schema/policy/interface identities, the existing standard Git LFS Batch API v2/basic-transfer baseline, and every deferred predecessor validation task. It MUST state `acceptance_proven=false`, `final_source_revision_bound=false`, `production_effect_authorized=false`, and `live_authorized=false`.

The gate permits only continued source, deferred-test, and documentation work. It MUST NOT be consumed as a capability lease, repository credential, LFS upload session, quota reservation, object-read proof, publication closure, publication intent, GC authority, production proof, live authorization, or remote-effect authorization. Final C5 acceptance SHALL re-read the combined final source and require the formal C1--C4 receipts plus every validation declared by this change.

#### Scenario: Continue C5 source work under unified deferred validation
- **WHEN** the C1 acceptance and current C2--C4 interfaces are snapshotted while final combined predecessor validation remains deferred
- **THEN** C5 may implement source and write tests without starting an LFS writer, performing Git/LFS I/O, publishing, deleting objects, running live work, or causing external effects

#### Scenario: Present the source-only gate as runtime authority
- **WHEN** a caller presents the gate to issue a credential, reserve quota, upload or read an object, admit a publication, pin a closure, or delete a GC candidate
- **THEN** the system rejects it and performs no fallback, retry, state transition, transfer, publication, or deletion

### Requirement: Repository binding fixes the Git LFS policy
The system MUST bind every Git LFS operation and publication validation to one immutable project repository binding version containing the LFS endpoint identity, path rules, ordinary-blob threshold, quotas, retention classes, object format, and policy digest. A session or publication intent MUST NOT substitute current global defaults when its pinned binding version is missing or differs.

#### Scenario: Session uses its pinned LFS policy
- **WHEN** an agent fetches or publishes from a session whose repository binding was fixed at creation
- **THEN** the system uses that exact binding version and policy digest even if a newer project policy exists

#### Scenario: Binding identity is incomplete
- **WHEN** the pinned binding lacks an LFS endpoint identity, object policy, or authoritative credential scope required by the revision
- **THEN** the Git LFS operation fails before transfer or publication and does not select another endpoint

### Requirement: Native clients use the standard Git LFS protocol
Podman agent workspaces and executor HPC login workspaces with an active capability lease MUST use native Git and Git LFS clients against the binding's standard Git LFS protocol. The system MUST NOT expose an agent-facing generic CAS, artifact catalog, Host typed transfer gateway, physical object-store locator, or custom pointer format. Compute nodes MUST receive resolved ordinary files without Git metadata, Git/LFS binaries, repository credentials, or direct LFS access.

#### Scenario: Agent fetches an LFS-backed revision
- **WHEN** an authorized agent runs native Git fetch and checkout for a revision containing valid LFS pointers
- **THEN** Git LFS retrieves the exact objects through the bound standard endpoint into that agent's private clone

#### Scenario: Compute tree contains an LFS file
- **WHEN** an HPC job is prepared from a revision whose closure includes an LFS object
- **THEN** the login-side preparation verifies and materializes the actual bytes into the Git-free compute tree without exposing an LFS credential to compute

### Requirement: Publication proves the complete Git LFS object closure
Before creating a `PublishedRevision`, the system MUST traverse the exact commit tree and validate every LFS pointer against the pinned repository policy. It MUST read every referenced object from the bound endpoint, verify its declared size and SHA-256 OID against actual bytes, and create a canonical sorted closure manifest binding normalized path, file mode, pointer blob OID, LFS OID, and size. The manifest digest MUST enter the publication identity.

#### Scenario: Complete closure is published
- **WHEN** every pointer is canonical and every referenced LFS object is readable with matching OID and size
- **THEN** publication records the exact closure manifest digest and creates the immutable published revision under the frozen intent

#### Scenario: Referenced object is missing
- **WHEN** one pointer references an object that the bound LFS endpoint cannot return completely
- **THEN** the publication intent fails without creating a `PublishedRevision` or substituting bytes from another repository or endpoint

#### Scenario: Object bytes disagree with the pointer
- **WHEN** the returned object length or SHA-256 digest differs from the pointer's size or OID
- **THEN** publication fails with the affected path and closed mismatch code and exposes no partial revision as shared truth

### Requirement: Oversized ordinary Git blobs are rejected explicitly
The publication validator MUST reject every non-LFS Git blob whose actual size exceeds the threshold fixed by the repository policy. The rejection MUST identify each normalized path, blob OID, observed size, threshold, and applicable rule. The system MUST NOT edit `.gitattributes`, rewrite the commit, upload a replacement LFS object, or create a substitute publication.

#### Scenario: Ordinary blob exceeds the threshold
- **WHEN** a clean commit contains a non-LFS blob larger than the pinned project threshold
- **THEN** publication fails with deterministic correction information and leaves the commit and attributes unchanged

#### Scenario: Agent corrects the commit explicitly
- **WHEN** the agent updates `.gitattributes`, recommits the file as a standard LFS pointer, and starts a new publication intent
- **THEN** the new intent is validated as a distinct commit without altering the failed intent

### Requirement: Quota failure does not change representation or destination
Git LFS upload and publication MUST enforce the repository binding's object, workspace, and repository quotas before accepting new retained bytes. A quota rejection MUST be explicit and MUST NOT fall back to a normal Git blob, a generic CAS, an alternate endpoint, or an untracked workspace-only success claim.

#### Scenario: LFS upload exceeds quota
- **WHEN** an agent attempts to upload an LFS object that would exceed an applicable pinned quota
- **THEN** the endpoint rejects the upload with a bounded quota fact and stores no published reference to the object

### Requirement: Published LFS objects remain pinned while private objects follow private retention
Every successful `PublishedRevision` MUST pin all Git and LFS objects in its verified closure against garbage collection. Objects reachable only from private refs, active workspace generations, or incomplete upload sessions MUST follow the pinned private retention policy. A private ref remains retained until the repository retention owner has retired its complete closed workspace-generation namespace through the immutable retirement receipt; expiration alone MUST NOT make selected checkpoints unreachable. Garbage collection MUST compute authorized reachability after validating any whole-generation retirement receipt and before deletion, and equal content digests MUST NOT confer cross-repository read or adoption authority.

#### Scenario: Published object outlives scratch retention
- **WHEN** a published LFS object is older than the private scratch retention period
- **THEN** garbage collection retains it because an immutable published revision still references its verified closure

#### Scenario: Unreachable private object expires
- **WHEN** an LFS object is unreachable from every publication pin, retained private ref, active workspace generation, and live upload session after its retention deadline
- **THEN** the object is eligible for deletion and garbage collection applies the bound repository policy

#### Scenario: Private namespace has not been validly retired
- **WHEN** a private checkpoint still belongs to a namespace without a valid whole-generation retirement receipt
- **THEN** its Git and LFS closure remains reachable even if a wall-clock retention deadline has passed

### Requirement: Native transfers remain private until explicit publication
An agent holding the relevant capability lease MUST be free to use native Git, Git LFS, curl, scp, rsync, and other allowed network tools without per-command approval. Bytes transferred by those tools MUST remain private workspace or private-ref state until the agent commits a clean whole-repository revision and an explicit `workspace.publish` succeeds. Transfer, commit, LFS upload, and private push MUST NOT by themselves create team-shared file truth or complete a task.

#### Scenario: Agent downloads a large private dataset
- **WHEN** an agent uses a native transfer tool to place bytes in its private workspace
- **THEN** the bytes remain private mutable files and no publication, artifact record, handoff, or task completion is created

#### Scenario: Agent pushes only a private ref
- **WHEN** an agent commits LFS-backed files and pushes its authorized private ref without invoking `workspace.publish`
- **THEN** other agents' shared projection remains unchanged and no `PublishedRevision` is created
