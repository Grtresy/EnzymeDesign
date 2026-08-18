# revision-path-handoff Specification

## Purpose
TBD - created by archiving change migrate-research-report-and-task-handoffs-to-files. Update Purpose after archive.
## Requirements
### Requirement: Source implementation does not promote deferred predecessor acceptance
During the explicitly ordered continuous migration, source implementation MAY begin from a `revision_path_handoff_source_only_dependency_gate@1` before final C2--C5 acceptance receipts are issued. The gate MUST bind immutable C1 acceptance, current C2--C5 source/schema/policy/interface identities, and every deferred predecessor validation task. It MUST state `acceptance_proven=false`, `final_source_revision_bound=false`, `production_effect_authorized=false`, and `live_authorized=false`.

The gate permits only continued source, deferred-test, and documentation work. It MUST NOT be consumed as a capability lease, credential, publication, handoff, report publication, task evidence, runtime command, production proof, live authorization, or remote-effect authorization. Final acceptance SHALL re-read the combined final source and require formal C1--C5 receipts plus every validation declared by this change.

#### Scenario: Continue source work under unified deferred validation
- **WHEN** immutable C1 acceptance and current C2--C5 source interfaces are snapshotted while final combined predecessor validation remains deferred
- **THEN** source migration may continue without publishing, delivering a protocol message, transitioning a task, issuing a credential, performing Git/LFS I/O, running live work, or causing an external effect

#### Scenario: Present the source-only gate as runtime authority
- **WHEN** a caller presents the gate to publish a workspace or report, send a handoff, finish a task, fetch a revision, issue a credential, or authorize production work
- **THEN** the system rejects it and performs no fallback, retry, state transition, transfer, publication, delivery, or task mutation

### Requirement: Revision path references have closed immutable identity
Every file handoff MUST use a versioned `RevisionPathRef` bound to a canonical `PublishedRevision`, repository binding version, exact commit and tree, normalized repository-relative path, entry kind, and exact Git object identity. A regular Git file MUST bind its blob OID and size; an LFS file MUST additionally bind its pointer blob OID, LFS OID, and size; a directory MUST bind its tree OID and canonical path-manifest digest. The system MUST reject absolute paths, traversal, mutable branches, private refs, URLs, Host paths, and identity drift.

#### Scenario: Resolve an exact published file
- **WHEN** a handoff contains a `RevisionPathRef` whose publication, commit, path, entry kind, and object identity all match canonical state
- **THEN** the recipient can resolve that exact immutable entry under the publication's repository authorization

#### Scenario: Branch is supplied instead of a publication
- **WHEN** a handoff supplies a branch and path without an immutable publication identity
- **THEN** validation rejects the handoff before protocol delivery or task evidence mutation

#### Scenario: Path identity drifts
- **WHEN** the referenced path resolves to a blob, tree, pointer, OID, or size different from the closed reference
- **THEN** the consumer fails closed and does not read another revision, legacy artifact, or EngineDocument copy

### Requirement: Persistent research work products are published files
Research source snapshots, citations, notes, analysis, dossiers, and tool outputs that must survive a turn or be consumed by another agent, report, or task MUST be written to the producer's workspace, committed in a clean revision, explicitly published, and handed off by `RevisionPathRef`. The system MUST NOT create a generic artifact alias or duplicate authoritative content bytes in an EngineDocument for those work products.

#### Scenario: Researcher hands off a dossier
- **WHEN** a researcher finishes a dossier needed by an executor
- **THEN** the researcher commits and publishes the dossier files and sends exact revision/path references

#### Scenario: Tool returns a large persistent result
- **WHEN** a tool result is too large for a bounded transient response and must be used later
- **THEN** the producing agent writes the result to its workspace and uses publication rather than an artifact alias or unbounded protocol payload

### Requirement: Protocol handoff carries bounded references and no file bytes
A protocol file handoff MUST contain a closed versioned payload with bounded producer, recipient, purpose, and `RevisionPathRef` entries. It MUST NOT embed file bytes, unbounded tool output, credentials, Host paths, HPC remote paths, mutable branches, or arbitrary URLs. `protocol.send` MUST persist the message and enqueue only its documented wakeup signal; it MUST NOT fetch, merge, run the recipient, or change task terminal status.

#### Scenario: Send a bounded file handoff
- **WHEN** a producer sends a valid list of published revision/path references within schema bounds
- **THEN** the inbox stores those exact references and no copy of the referenced bytes

#### Scenario: Payload embeds file bytes
- **WHEN** a handoff attempts to include an unbounded file body instead of a typed reference
- **THEN** protocol validation rejects the message without converting the body to an artifact or workspace file

### Requirement: Recipient fetches the exact publication with native Git
An authorized recipient MUST use native Git and Git LFS to fetch the immutable publication ref and MUST verify the received commit, path, and object identity against each `RevisionPathRef`. The system MUST leave merge, rebase, cherry-pick, copy, and read-only inspection choices to the recipient and MUST NOT automatically update its clone or substitute a Host file-transfer gateway.

#### Scenario: Recipient inspects without merging
- **WHEN** a recipient fetches a valid published revision and chooses to inspect its files without changing the current branch
- **THEN** the exact revision is available in the recipient's private clone and no merge or task transition occurs

#### Scenario: Native fetch fails
- **WHEN** Git or Git LFS cannot retrieve the exact immutable publication
- **THEN** the handoff remains unresolved and no artifact, alternate ref, or copied bytes are used as a fallback

### Requirement: Task completion evidence is a closed typed union
`task.finish` MUST accept only a versioned closed evidence union containing `RevisionPathRef`, `ReportRef`, `ControlledOperationResultRef`, or `ScientificDeliverableRef`. Every reference MUST resolve to its canonical immutable owner and be authorized for the task's project and session. The system MUST reject `artifact:<id>`, bare mutable paths, branches, private refs, URLs, Host/HPC paths, free-form digests, and unknown variants.

#### Scenario: Finish with published file evidence
- **WHEN** an agent explicitly finishes a task with an authorized exact `RevisionPathRef`
- **THEN** the task records that typed evidence and the agent's terminal decision without duplicating file bytes

#### Scenario: Finish with a mutable path
- **WHEN** an agent calls `task.finish` with only a workspace path or branch name
- **THEN** the call is rejected and the task remains nonterminal

#### Scenario: Evidence exists but agent has not finished
- **WHEN** a valid publication, report, or controlled-operation result becomes available
- **THEN** any projection or delivery contains only the typed evidence and does not mechanically complete the task

### Requirement: Report publication binds an exact published file
`report.publish` MUST accept an authorized `RevisionPathRef` for the report body and MUST verify its publication, commit, path, object identity, allowed file type, and report ownership before creating the report business publication. It MUST NOT read dirty workspace content, invoke `workspace.publish`, push a ref, create an alternate revision, or treat the whole repository as the report. A report correction MUST bind a new published revision/path and create an explicit new report version or supersession.

#### Scenario: Publish a report from a published file
- **WHEN** a reporter has explicitly published a clean report file and invokes `report.publish` with its exact reference
- **THEN** the report business record binds that immutable file identity without performing another workspace publication

#### Scenario: Report file is only private
- **WHEN** `report.publish` receives a dirty path, local commit, or private ref that has no canonical `PublishedRevision`
- **THEN** report publication fails and does not publish the workspace implicitly

#### Scenario: Correct a published report
- **WHEN** a reporter changes report content after a prior report publication
- **THEN** the reporter must create a new clean publication and explicit report version while the prior report body identity remains immutable

### Requirement: Handoff facts do not imply downstream business transitions
Creating, sending, fetching, or reading a `RevisionPathRef`, publishing a report, or receiving controlled-operation evidence MUST NOT automatically merge a clone, run a recipient turn, complete or fail a task, close a scientific attempt, adopt a scientific deliverable, or select a workflow result. Those transitions MUST remain owned by their documented agent or control-plane services.

#### Scenario: Recipient receives research files
- **WHEN** a protocol message containing valid research file references reaches an executor inbox
- **THEN** the executor remains free to fetch, inspect, request clarification, delegate, or continue its task and is not synchronously run or completed

#### Scenario: Report becomes published
- **WHEN** `report.publish` successfully binds an exact published file
- **THEN** report state advances while unrelated tasks and scientific attempts remain unchanged
