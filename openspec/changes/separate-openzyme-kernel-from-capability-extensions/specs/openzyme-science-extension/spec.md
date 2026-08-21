## ADDED Requirements

### Requirement: Scientific lifecycle is owned by an optional extension
`openzyme-science` MUST own ScientificAttempt, Selection, Occurrence, Disposition, Adoption, ScientificDeliverable, validation receipt, formal closure, selection evaluation and attempt rollover. Contracts and Kernel MUST NOT require those types or initialize their state for a non-scientific Session.

#### Scenario: Start a non-scientific Standard Session
- **WHEN** Standard activates without the Science extension
- **THEN** Session, Task, Agent, Approval, runtime and file publication work without importing a scientific type or creating a scientific table

#### Scenario: Activate Science
- **WHEN** an exact Science manifest and migrations are selected
- **THEN** its lifecycle services, tools, validators and projection register under the Science contract ID without changing Core schemas

### Requirement: Scientific attempts preserve exact identity and owner
Every ScientificAttempt and its selection/occurrence/disposition/adoption/deliverable facts MUST bind exact Session, Task where applicable, attempt generation/scope, owner, workflow contract/digest and source evidence identities. Cross-attempt, cross-generation or cross-Session substitution MUST be rejected.

#### Scenario: Adopt an occurrence from the current attempt
- **WHEN** the authorized scientific owner adopts a verified occurrence whose attempt, generation and workflow contract match
- **THEN** Science records the adoption in its namespace with the same immutable evidence identities

#### Scenario: Cross-attempt evidence is supplied
- **WHEN** a finalization command references a deliverable or occurrence from another attempt or generation
- **THEN** Science rejects it before mutation and does not copy or reinterpret the evidence

### Requirement: Science state mutations use Kernel authority and extension transactions
Every Science command MUST be admitted through Kernel identity, AgentAuthorityLease, approval and fence rules, then mutate only the Science namespace through a declared transaction participant. Science MUST NOT receive CoreRepositories or write Session, Task, Approval, publication or controlled-operation tables directly.

#### Scenario: Atomic scientific adoption
- **WHEN** a valid Kernel command requires a Science adoption and a generic Core evidence link in one transition
- **THEN** both changes commit through one bounded Unit of Work or both roll back

#### Scenario: Stale scientific writer
- **WHEN** a Science worker uses a stale attempt generation, authority lease or mutation fence
- **THEN** Kernel/participant admission rejects it with no Science or Core mutation

### Requirement: Scientific deliverables are immutable file references
A ScientificDeliverable MUST reference verified PublishedRevision and RevisionPathRef identities plus its scientific role/contract metadata. Science MUST NOT own artifact storage, Host paths, mutable private files or an implicit materialization path.

#### Scenario: Finalize a file deliverable
- **WHEN** all required scientific roles resolve to verified paths in the exact publication and validation succeeds
- **THEN** Science records a deliverable receipt bound to those immutable path/content identities

#### Scenario: Published bytes drift or are unavailable
- **WHEN** a referenced path, object type, content digest, size or LFS closure fails verification
- **THEN** finalization fails without adopting another revision, fetching from an undeclared source or finishing a Task

### Requirement: Formal scientific closure remains explicit and atomic
Formal closure MUST occur only through the declared Science application command after exact attempt, workflow, selection, occurrence, adoption and deliverable validation. Validation receipt existence alone MUST NOT close an attempt; partial closure MUST roll back.

#### Scenario: Close a complete formal attempt
- **WHEN** the authorized owner submits a complete exact closure command
- **THEN** all Science terminal facts commit atomically and the receipt identifies the exact input closure

#### Scenario: One required occurrence is missing
- **WHEN** formal closure lacks a required occurrence or contains conflicting disposition
- **THEN** no partial attempt/deliverable/selection terminal mutation commits

### Requirement: Science finish validation does not own Task terminal
Science MAY provide a Task finish validator that verifies scientific closure/evidence for an explicitly requested `task.finish`. The validator MUST be read-only for Core and MUST NOT enqueue finish, change Task status or infer Task completion from attempt closure.

#### Scenario: Attempt closes before the Task
- **WHEN** Science records a valid formal closure but the Task owner has not called `task.finish`
- **THEN** the Task remains non-terminal

#### Scenario: Owner explicitly finishes after closure
- **WHEN** the Task owner calls `task.finish` with the exact Science receipt required by its validator
- **THEN** Science returns acceptance and Kernel remains the sole writer of Task terminal state

### Requirement: Science projection is extension-namespaced and model-blind
Science state MUST appear only under its exact `@2` extension contract with bounded attempt, selection, occurrence, adoption, deliverable and closure facts. Core reducers and runtime coordination MUST NOT inspect scientific fields to choose Agent strategy, auto-wake a specific workflow or infer business terminal state.

#### Scenario: Project a scientific attempt
- **WHEN** an authorized caller reads a Science-enabled Session
- **THEN** the extension section exposes safe exact identities and statuses without raw bytes, credentials, provider logs or Core shadow fields

#### Scenario: Runtime sees a Science receipt
- **WHEN** a Science outcome wakes its owning Agent
- **THEN** runtime records a generic capability-outcome wake fact and does not auto-finish, retry or select the next scientific operation

### Requirement: Science policies remain general rather than Enzyme-specific
Science MUST define reusable lifecycle and validator seams but MUST NOT contain AOX reference data, enzyme-specific roles, HMMER/motif thresholds, docking rules, protein database clients or enzyme acceptance templates. Those policies MUST be registered by EnzymeDesign extensions.

#### Scenario: Register an AOX workflow contract
- **WHEN** EnzymeDesign activates an AOX scientific workflow contract
- **THEN** Science validates it through generic workflow/role interfaces while AOX schemas and thresholds remain in the EnzymeDesign distribution

#### Scenario: Vertical vocabulary leaks into Science
- **WHEN** source or wheel inspection finds AOX/HMMER/Vina/fpocket/AlphaFold/RDKit-specific implementation in base Science
- **THEN** layered qualification fails

### Requirement: Science implementation and documentation share one owner map
Scientific types, repositories, migrations, tools, projections, Host routes, tests and stable documentation MUST be migrated together to the Science extension. Any Core document or public import that still claims ownership, or any Science README that omits lifecycle/finish separation, MUST block completion.

#### Scenario: Source moved but control-plane docs are stale
- **WHEN** Science repositories are extension-owned while `docs/v3/02-control-plane.md` still lists them as Kernel canonical tables without extension qualification
- **THEN** source-to-document drift validation fails

#### Scenario: Documentation reflects the split
- **WHEN** current source, table-owner manifest, Science contract, main architecture and relevant V3 docs identify the same owners and terminal boundaries
- **THEN** the Science documentation slice is accepted
