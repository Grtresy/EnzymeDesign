## ADDED Requirements

### Requirement: Scientific selections preserve the complete occurrence universe
The Host SHALL derive a complete, digest-bound universe of all controlled operations and covered sandbox runs in one exact scientific attempt and scope. A selection MUST NOT be sealed unless every occurrence in that universe has exactly one current disposition of `adopted`, `superseded`, `failed`, or `abandoned`.

#### Scenario: Seal a fully dispositioned universe
- **WHEN** every Host-derived occurrence has one valid disposition and the universe digest remains stable
- **THEN** the selection may proceed to workflow and effect validation

#### Scenario: Omit an extra operation
- **WHEN** an operation exists in canonical history but is absent from the submitted disposition set
- **THEN** selection sealing fails and identifies the missing occurrence without deleting or ignoring it

### Requirement: The agent explicitly owns adoption and supersession
Only an authorized agent or operator command SHALL assign scientific dispositions and adopted workflow roles. The Host MUST validate real constraints but MUST NOT infer adoption from recency, successful status, equal bytes, downstream use, workspace paths, or report text.

#### Scenario: Two completed operations have equal output bytes
- **WHEN** two completed operations produce the same digest
- **THEN** they remain distinct occurrences and the agent must adopt one and explicitly dispose the other

#### Scenario: Harness sees a latest success
- **WHEN** a failed occurrence is followed by a successful replacement
- **THEN** the Host does not automatically select the later operation or erase the failure

### Requirement: Effect adoption is same-attempt and certainty-gated
An adopted effect MUST reference a terminal immutable controlled-operation result in the same formal attempt and exact scope, with effect certainty, approval, inputs, backend, runtime, expected outputs, and workflow role satisfying the bound contract. `dispatch_in_doubt`, active, unreconciled, unauthorized, or cross-attempt effects MUST block adoption.

#### Scenario: Adopt a completed upstream effect across runs
- **WHEN** run A produced a terminal known effect and run B belongs to the same formal attempt and scope
- **THEN** an explicit adoption may reference run A without manufacturing a second completed operation

#### Scenario: Attempt cross-scope reuse
- **WHEN** a formal selection references an operation from another attempt, campaign, positive, probe, or fault scope
- **THEN** adoption fails closed even if the artifact bytes are identical

### Requirement: Artifact materialization is Host supervised
Using an adopted artifact in another sandbox run SHALL require a Host-owned materialization command that revalidates catalog identity, sealed bytes and digest, read grant, source attempt/scope, target workspace authority, target path policy, and overwrite policy. The resulting immutable receipt MUST bind source and target identities.

#### Scenario: Materialize adopted bytes into a fresh run
- **WHEN** an authorized same-attempt target requests a sealed adopted artifact
- **THEN** the Host copies or mounts the verified bytes and records a receipt consumable by the downstream lineage verifier

#### Scenario: Reuse a checkpoint path without a receipt
- **WHEN** a sandbox reads a shared path or attempt-local checkpoint but no valid materialization receipt authorizes it
- **THEN** the bytes cannot enter the adopted scientific chain

### Requirement: Selection revisions are immutable and CAS protected
Each selection revision SHALL have a new identity, monotonically increasing revision, optional parent, immutable disposition/adoption digests, actor, and lifecycle state. A sealed revision MUST NOT be edited; a replacement revision MUST use compare-and-swap against the current head and MUST NOT invalidate a revision already consumed by closure or evidence.

#### Scenario: Concurrent agents update one selection
- **WHEN** two writers submit changes from the same parent revision
- **THEN** at most one becomes the next head and the other receives a version conflict

#### Scenario: Change a sealed unconsumed selection
- **WHEN** an agent needs to revise a sealed selection before closure
- **THEN** it creates a linked new revision and the prior immutable revision remains auditable

### Requirement: Attempt closure is explicit and complete
The Host SHALL create an immutable scientific attempt closure only when the selected workflow chain is valid, every occurrence is dispositioned, all adopted effects and materializations verify, no external effect or authority remains unknown, all covered processes/writers are retired, authorization consumption is valid, and an exact quiescence receipt seals the same scope generation. Closure MUST NOT complete or fail the task.

#### Scenario: Close after known trial and error
- **WHEN** failed and superseded operations are terminal and explicitly disposed, one adopted chain verifies, and quiescence is proven
- **THEN** the attempt may close successfully without treating the known closed failures as adopted evidence

#### Scenario: Unknown effect remains
- **WHEN** any occurrence is `dispatch_in_doubt` or unreconciled
- **THEN** attempt closure fails closed and a new attempt cannot bypass the blocker

#### Scenario: Closure succeeds before task finish
- **WHEN** a scientific attempt closure is sealed
- **THEN** task status remains unchanged until an agent explicitly performs a canonical task transition

### Requirement: Scientific selection commands and projections are authority safe
Selection, disposition, adoption, materialization, sealing, and closure commands SHALL be actor-bound, idempotent, session/task scoped, and validated by the control plane. Public projections MUST expose complete safe occurrence/disposition/closure facts and evidence ids while withholding grants, fences, Host paths, credentials, backend handles, and private diagnostics.

#### Scenario: Inspect an attempt with failed occurrences
- **WHEN** a user opens an attempt workspace
- **THEN** the projection shows the adopted chain and every failed/superseded/abandoned occurrence with bounded reasons

#### Scenario: Replay a disposition command
- **WHEN** the same actor repeats an identical disposition command with the same idempotency key
- **THEN** the existing record is returned without creating a divergent revision
