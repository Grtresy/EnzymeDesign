# workspace-publication Specification

## Purpose
TBD - created by archiving change publish-and-sync-workspace-revisions. Update Purpose after archive.
## Requirements
### Requirement: Source implementation does not promote deferred predecessor acceptance
During the explicitly ordered continuous migration, C4 source implementation MAY begin from a `workspace_publication_source_only_dependency_gate@1` before final C2/C3 acceptance receipts are issued. The gate MUST bind immutable C0/C1 receipt identities, current C2/C3 source, schema, policy and interface identities, the controlled-operation baseline, and all deferred predecessor validation tasks. It MUST state `acceptance_proven=false`, `final_source_revision_bound=false`, `production_effect_authorized=false`, and `live_authorized=false`.

The gate permits only continued source, deferred-test, and documentation work. It MUST NOT be consumed as an active capability lease, ready workspace, checkpoint proof, controlled execution owner or fence, Git credential, publication receipt, production proof, live authorization, or remote-effect authorization. Final C4 acceptance SHALL re-read the combined final source and require the formal C0--C3 receipts plus every validation declared by this change.

#### Scenario: Continue C4 source work under unified deferred validation
- **WHEN** current C2/C3 interfaces and the controlled-operation baseline are snapshotted while their final combined validation remains deferred
- **THEN** C4 may implement source and write tests without running production publication, remote Git I/O, live work, or external effects

#### Scenario: Present the source-only gate as runtime authority
- **WHEN** a caller presents the gate to admit or dispatch a publication, issue a credential, create a remote ref, or claim predecessor acceptance
- **THEN** the system rejects it and performs no fallback, retry, state transition, or external effect

### Requirement: Publication requires an explicit clean whole-repository intent
`workspace.publish` SHALL accept only an explicit intent bound to the exact repository binding version, agent, workspace generation, expected HEAD commit, tree, declared base or parent, whole-repository path manifest, current policy digest, and idempotency key. Before any remote effect, the Host MUST prove that the working tree has no staged, unstaged, or untracked changes, HEAD equals the requested commit, and the commit belongs to the pinned repository. It MUST NOT stage, commit, clean, ignore, rewrite, or partially package the workspace.

#### Scenario: Publish a clean exact HEAD
- **WHEN** an authorized agent explicitly publishes its clean workspace at the exact expected HEAD under the pinned binding and current policy
- **THEN** the Host freezes one whole-repository publication intent before dispatching a remote ref operation

#### Scenario: Publish a dirty workspace
- **WHEN** the workspace contains staged, unstaged, or untracked changes
- **THEN** admission reports the exact dirty state and creates no publication intent, remote ref, or shared projection

#### Scenario: Publish a path subset
- **WHEN** a caller requests publication of selected files without the complete commit tree
- **THEN** admission rejects the request and does not create an archive, artifact, synthetic commit, or partial publication

### Requirement: C4 composes publication intent, capability lease, and controlled execution without substitution
C4 SHALL implement the real publication authority composition and SHALL consume C2 only for the canonical exact `AgentCapabilityLease` identity, profile, generation, and current status. Before creating a publication execution, admission MUST have one exact frozen publication intent and an active matching lease. Those two facts SHALL create or reread exactly one publication-bound `ControlledOperationExecution`, but remote Git I/O MUST remain forbidden until that execution is durable and its current execution owner, fence, state version, and mutation authority are valid. A lease, intent, execution token, publication ref, or prior receipt MUST NOT imply either missing axis. No generic budget or retry counter SHALL count as publication authority.

If C2 reports the exact lease inactive before any possible remote effect, C4 MUST close new dispatch with `no_effect`. If revoke occurs only after dispatch may have happened, C4 MUST stop new dispatch but SHALL keep the original execution responsible for exact-ref reconciliation and materialization of the already-proven publication; revoke MUST NOT be interpreted as remote no-effect or permission to create a replacement execution/ref. C4 SHALL consume C2's canonical revoke outcome without reimplementing exact, session/policy bulk, operator-subtree, or parent/child selection semantics.

#### Scenario: Lease exists without publication intent
- **WHEN** an agent has an active Git-capable lease but supplies no exact frozen publication intent
- **THEN** C4 creates no publication execution, remote ref, receipt, or shared revision

#### Scenario: Intent exists without an active exact lease
- **WHEN** a publication intent is frozen but the exact agent/workspace-generation lease is missing, inactive, or profile-mismatched at admission
- **THEN** C4 rejects admission before creating an execution or performing Git I/O

#### Scenario: Intent and lease create one execution
- **WHEN** the exact intent and active matching lease pass C4 admission and no execution exists
- **THEN** C4 atomically creates or rereads exactly one intent-bound `ControlledOperationExecution` without opening a per-publication human approval

#### Scenario: Existing execution does not match the other axes
- **WHEN** a supplied or recovered execution names a different intent, binding, publisher, workspace generation, commit, manifest, or policy, or lacks the current execution fence
- **THEN** C4 reports an identity or fence conflict and performs no remote ref operation or shared-truth mutation

#### Scenario: Lease is revoked before publication dispatch
- **WHEN** C2 reports the exact lease inactive before the execution has any possible remote effect
- **THEN** C4 closes that execution with `effect_certainty = no_effect` and does not switch leases, reopen approval, or create another ref

#### Scenario: Lease is revoked after publication may have dispatched
- **WHEN** the exact ref operation may have occurred before C2 reports the lease inactive
- **THEN** the original fenced execution reconciles only its preallocated ref and may materialize only the publication proved by that intent, with zero new dispatches

### Requirement: Published revisions bind exact immutable repository facts
After exact remote-ref confirmation, the Host SHALL create one append-only `PublishedRevision` binding the publication id, project and session, repository binding version, exact commit and tree, Git parent commits, declared base or parent publication, publisher and workspace generation, immutable publication ref, canonical whole-tree path manifest and digest, policy digest, frozen intent, controlled execution, exact remote receipt, timestamp, and optional `supersedes` identity. The record and remote ref MUST NOT be updated, force-moved, or deleted.

#### Scenario: Materialize a confirmed publication
- **WHEN** the Host proves that the preallocated immutable ref points to the exact intended commit
- **THEN** it persists one `PublishedRevision` whose commit, tree, manifest, policy, publisher, intent, execution, and receipt all agree

#### Scenario: Correct a published revision
- **WHEN** a publisher needs to replace previously shared content
- **THEN** the publisher creates a new clean commit and publication with `supersedes` pointing to the old publication while both immutable records and refs remain readable

#### Scenario: Attempt to force-update or delete a publication
- **WHEN** any agent or Host path requests mutation or deletion of an existing publication ref or record
- **THEN** the repository or remote ACL rejects the request before changing shared truth

### Requirement: Only canonical publication changes team shared truth
Local file edits, local commits, local branches, and pushes to agent-private refs MUST remain private workspace state and MUST NOT appear as team shared revision truth. Team projection SHALL expose a revision only after its exact remote effect is confirmed and its canonical `PublishedRevision` is durable; it MUST NOT infer publication by scanning remote branches or private refs.

#### Scenario: Push a private commit
- **WHEN** an agent pushes a commit to its authorized private namespace
- **THEN** no team publication, shared revision, protocol message, or task transition is created

#### Scenario: Remote ref exists without a materialized record during recovery
- **WHEN** recovery finds the exact preallocated publication ref after response or database-commit loss
- **THEN** it reconciles the frozen intent and exact ref before materializing the same canonical publication and does not expose the ref by remote scanning alone

### Requirement: Publication effects have one owner and honest certainty
Each publication intent MUST automatically create and bind exactly one canonical `ControlledOperationExecution` as the owner of the create-only remote ref effect through C4's three-axis composition after validating the active capability lease and frozen explicit intent. `workspace.publish` MUST NOT require another per-publication human approval. The Host SHALL persist dispatch intent before I/O, use a Host-only credential and compare-and-set ref creation, and record an exact receipt binding remote identity, ref, expected absence, and new commit. Response loss MUST be reconciled only against that exact ref and intent; the Host MUST NOT automatically retry a push, choose another remote or ref, create a replacement publication, or reopen publication intent.

#### Scenario: Remote confirms create-only ref update
- **WHEN** the Git service confirms that the preallocated absent ref was created at the exact intended commit
- **THEN** the controlled execution records a known effect and the Host materializes the same publication once

#### Scenario: Response is lost after dispatch
- **WHEN** the Host cannot tell whether the Git service accepted the create-only ref update
- **THEN** the execution records `dispatch_in_doubt` and reconciliation queries only the preallocated exact ref without issuing another push

#### Scenario: Exact ref already contains the intended commit
- **WHEN** reconciliation proves that the preallocated ref exists at the exact intent commit
- **THEN** the same execution and publication converge to success without a replacement ref or duplicate `PublishedRevision`

#### Scenario: Exact ref contains another commit
- **WHEN** reconciliation observes the preallocated ref at a commit different from the frozen intent
- **THEN** the operation fails with an integrity conflict and neither commit is silently adopted or overwritten

### Requirement: Idempotency rejects publication identity drift
The Host SHALL bind each idempotency key to one immutable publication intent. Reusing the key with the identical repository binding, workspace generation, commit/tree, base/parent, manifest, policy, publisher, and supersedes identity MUST return the same intent/execution/publication state. Reusing it with any changed field MUST fail before remote I/O.

#### Scenario: Repeat an identical publish request
- **WHEN** a caller repeats the exact publish request with the same idempotency key after response loss
- **THEN** the Host returns or reconciles the original intent and never allocates another publication id or ref

#### Scenario: Reuse a key for a new commit
- **WHEN** a caller changes the commit, tree, manifest, parent, policy, publisher, or workspace generation while retaining the same key
- **THEN** the Host reports idempotency identity drift and performs no remote operation

### Requirement: Synchronization is explicit and agent-owned
An agent SHALL obtain another agent's work by explicitly fetching the exact immutable ref named by a `PublishedRevision` into its own clone and verifying the fetched commit and tree. Fetch MUST NOT automatically checkout, fast-forward, merge, rebase, cherry-pick, resolve conflicts, alter task state, or select a fallback revision. Any integration operation SHALL remain an explicit agent Git action.

#### Scenario: Fetch a published revision for inspection
- **WHEN** an agent explicitly fetches a publication id whose ref, commit, and tree match the team projection
- **THEN** the objects become available in that agent's clone while its current branch and working tree remain unchanged

#### Scenario: Integration conflicts
- **WHEN** an agent explicitly merges, rebases, or cherry-picks a fetched publication and Git reports conflicts
- **THEN** the conflict is returned to the agent and the Host does not choose another strategy, revision, or automatic retry

#### Scenario: Fetched identity mismatches projection
- **WHEN** the fetched ref, commit, or tree differs from the canonical `PublishedRevision`
- **THEN** synchronization fails closed and does not checkout or integrate the mismatched revision

### Requirement: Publication references support handoff without causing workflow transitions
Protocol and task evidence SHALL be able to reference an exact `publication_id + revision + repository-relative path`, and consumers MUST verify that the revision and path occur in the publication's canonical manifest. Publishing MUST NOT automatically send a protocol message, enqueue a wakeup, satisfy a dependency, fetch into another clone, or complete, fail, block, cancel, or resume a task.

#### Scenario: Send an exact handoff reference
- **WHEN** a researcher explicitly sends a handoff containing a valid publication, exact commit, and path present in its manifest
- **THEN** the recipient can verify and explicitly fetch that revision without copied bytes or a mutable branch name

#### Scenario: Publish without sending a handoff
- **WHEN** `workspace.publish` completes successfully and the publisher takes no protocol or task action
- **THEN** the publication becomes shared revision truth while inboxes, wakeups, dependencies, and task statuses remain unchanged

#### Scenario: Reference a missing path
- **WHEN** a handoff names a path absent from the exact publication manifest
- **THEN** validation rejects the handoff reference and does not substitute a similarly named path or another revision
