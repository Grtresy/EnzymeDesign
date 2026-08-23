## ADDED Requirements

### Requirement: Contracts wheel is implementation-free
`openzyme-contracts` MUST contain only stable cross-domain identities, enums, DTOs, closed failure/tool/extension contracts and application ports. Importing or installing it MUST NOT require SQLite, FastAPI, LangChain, a model/provider SDK, Git execution, a process/container runtime, Research, Reporting, Science, HPC or EnzymeDesign libraries.

#### Scenario: Install Contracts alone
- **WHEN** a fresh environment installs and imports the built `openzyme-contracts` wheel
- **THEN** wheel metadata and imported modules contain no implementation or vertical dependency and perform no filesystem, database, process or network initialization

#### Scenario: Implementation type leaks into a port
- **WHEN** a public Contracts annotation or serialized DTO refers to a FastAPI, SQLite, LangChain, provider, Git implementation, scientific or HPC type
- **THEN** the dependency-boundary gate fails and the contract cannot be accepted

### Requirement: Kernel owns canonical collaboration truth
`openzyme-kernel` MUST be the sole application owner for Project/Session, Task/Dependency/Finish, Lane, AgentMember and parent-child membership, Delegation, Inbox, Protocol, canonical conversation facts, Memory and Agent retirement settlement. No adapter or extension MAY create an alternate reducer or write path for those facts.

#### Scenario: Complete a task through its owner
- **WHEN** the authorized Task owner explicitly invokes `task.finish` with evidence accepted by every bound validator
- **THEN** the Kernel application service performs the terminal mutation and emits the canonical event in one authorized Unit of Work

#### Scenario: Extension attempts a direct task write
- **WHEN** an extension repository, worker, receipt handler or projection attempts to update a Core Task row or emit a canonical Task terminal event
- **THEN** the operation is rejected before mutation and a structured authority-boundary failure identifies the extension and forbidden target

### Requirement: Kernel owns generic authority and reliability semantics
The Kernel MUST own ApprovalRequest, AgentAuthorityLease, owner/generation/lease/fence, idempotency identity, mutation writer/quiescence/settlement, durable event and failure observation semantics. `AgentCapabilityLease` MUST be removed from the public `@2` vocabulary; the initial cutover MAY preserve legacy physical table names only behind the store adapter and migration ledger. An Adapter MAY implement credentials or transport, but MUST NOT redefine authority, stale-writer acceptance or canonical effect certainty.

#### Scenario: Reject a stale writer across adapters
- **WHEN** any runtime, workspace or effect adapter returns a mutation using an expired lease generation, stale fence or wrong owner
- **THEN** the Kernel rejects it with no canonical mutation and records the exact identity mismatch

#### Scenario: Credential success is not authority
- **WHEN** a Git, provider, process or SSH Adapter possesses usable credentials but the associated authority lease or approval is absent
- **THEN** admission fails before the external dispatch and credential possession is not treated as authorization

#### Scenario: Bootstrap the first Session without an impossible preseeded lease
- **WHEN** an authenticated operator creates a fresh Session whose master Agent and root lease do not yet exist
- **THEN** a narrow bootstrap-authority Port verifies a short-lived authorization bound to the exact project, Session, root AgentAuthorityLease, revision-1 Session capability binding and immutable composition pin, and the Kernel creates all five canonical facts plus its durable event in one Unit of Work
- **AND** the ordinary collaboration create path cannot substitute a fabricated Session-bound Agent lease, while denial, expiry, digest drift or any owner conflict leaves every bootstrap fact absent

#### Scenario: Reuse a physical table without reusing legacy semantics
- **WHEN** the SQLite Adapter stores target authority, approval, runtime-signal, Session-lease, continuation or controlled-operation state in a retained physical table
- **THEN** a closed record kind or target identity and explicit target columns separate it from historical rows, the codec reconstructs canonical state only from those target columns and the CAS ledger contains no payload JSON
- **AND** legacy callback names are deny-only in the target ControlStore while target claim, fence and effect checks use current structured authority facts, so no legacy Core import or fabricated compatibility payload can authorize the mutation

### Requirement: Kernel owns extension and capability resolution truth
The Kernel MUST own the activated ExtensionBundleRegistry, CapabilityRegistry, capability/dependency resolution, SessionCapabilityBindingRevision and ToolAffordanceResolver. It MUST persist only safe component, capability, route, qualification and blocker identities supplied through `openzyme-extension-spi`; it MUST NOT import or interpret Plugin domain classes or concrete Adapter implementations.

#### Scenario: Resolve a target-backed tool
- **WHEN** a declared tool, active Plugin, adopted target inventory, route, AgentAuthorityLease and ready workspace satisfy all exact requirements
- **THEN** the Kernel emits an immutable available ToolAffordance bound to those identities

#### Scenario: Capability provider disappears
- **WHEN** dispatch revalidation cannot prove the same route, inventory generation, authority lease and workspace generation named by the affordance snapshot
- **THEN** the Kernel rejects dispatch with `tool_affordance_stale`, `effect_certainty = no_effect` and `fallback_performed = false`

### Requirement: Kernel owns runtime coordination but not runtime mechanism
The Kernel MUST own durable AgentRuntimeSignal, signal claim, SessionRuntimeLease, bounded runtime command/outcome identity, continuation delivery, process epoch/fence, settlement and retirement fencing. It MUST consume runtime behavior only through the runtime SPI and MUST NOT import a concrete LLM, provider, prompt framework or process/container adapter.

#### Scenario: Run a bounded fake turn
- **WHEN** Kernel qualification claims a signal and invokes a deterministic fake runtime adapter
- **THEN** the same lease, command, outcome, continuation and settlement state machine executes without LangChain, a Provider, Podman or subprocess dependency

#### Scenario: Runtime ends without task finish
- **WHEN** a runtime outcome is idle, step-limited, failed or successfully consumed but contains no authorized `task.finish` command
- **THEN** the Task terminal state remains unchanged

### Requirement: Kernel owns Git-shaped immutable handoff semantics
The Kernel MUST own repository-binding identity and Session pin, WorkspaceGeneration, private checkpoint, publication intent, immutable PublishedRevision, commit/tree/LFS-closure identity, RevisionPathRef, verified handoff and generic EvidenceRef semantics. It MUST NOT execute Git commands or own ref layout, credentials, repository roots, LFS storage, pin/GC or mount mechanisms.

#### Scenario: Publish an exact revision through an adapter
- **WHEN** an authorized publication command names a clean commit, tree and verified LFS closure returned by the configured workspace adapter
- **THEN** the Kernel records one immutable PublishedRevision and its authority/identity receipt without learning a Host repository path or credential

#### Scenario: Later private edits do not alter a handoff
- **WHEN** a verified RevisionPathRef names an existing PublishedRevision and the producer later changes its private workspace
- **THEN** handoff verification remains bound to the published commit/tree/path and does not inspect or modify the later private state

#### Scenario: Persist publication truth without Adapter table authority
- **WHEN** the SQLite Adapter commits a verified checkpoint, publication intent, PublishedRevision or revision-path verification receipt
- **THEN** its owner codec and database constraints validate only Kernel workspace generation/runtime binding, Agent/authority, repository binding/pin and generic controlled-operation facts
- **AND** no target foreign key or trigger reads a Git workspace mechanism table, Adapter remote-receipt repository or legacy publication-execution table as canonical authority

### Requirement: Kernel owns Workspace Runtime contracts but not mechanisms
The Kernel MUST own WorkspaceRuntimeBinding, root-relative observation/filesystem/process/transfer requests, operation-specific authority admission, generation/fence checks, durable mutation/effect receipts and bounded failure semantics. It MUST expose separate Ports for observation, structured filesystem mutation, bounded process execution and transfer, while local filesystem, Git/LFS, Podman, SSH, SFTP and rsync mechanisms remain Adapters and remote workspace lifecycle remains an HPC Plugin concern.

#### Scenario: Execute in the current local workspace
- **WHEN** an authorized Agent invokes `workspace.exec` and the Kernel resolves its unique ready local WorkspaceRuntimeBinding
- **THEN** dispatch uses the selected local process Adapter, binds the exact workspace generation and never interprets the call as an HPC or SSH operation

#### Scenario: Attempt a path escape
- **WHEN** a filesystem request includes an absolute path, `..`, wildcard expansion or a symlink escape beyond the bound root
- **THEN** admission rejects it with `effect_certainty = no_effect` and no Adapter mutation occurs

### Requirement: Kernel owns one generic controlled-operation lifecycle
The Kernel MUST own admission, intent digest, approval binding, dispatch identity, `no_effect`/`dispatch_in_doubt`/`settled` certainty, observe/reconcile, deadline, cancel intent, result handle, terminal receipt and stale-fence rejection for external effects. Extensions MUST use this lifecycle and MUST NOT create a second effect-certainty state machine.

#### Scenario: Provider dispatch response is lost
- **WHEN** an extension adapter may have accepted an exact dispatch but its response is lost
- **THEN** the Kernel preserves `dispatch_in_doubt`, requires identity-bound observation or reconciliation and never authorizes a replacement dispatch merely because the extension retries

#### Scenario: Pre-effect rejection is proven
- **WHEN** admission proves that no external effect occurred
- **THEN** the occurrence may settle as `no_effect` without completing its Task or inferring the outcome of any other occurrence

### Requirement: Kernel tool and invocation contracts are domain-neutral
The Kernel MUST own canonical dotted tool names, ToolSpec, ToolResult, JSON Schema validation, declared-catalog and affordance-snapshot identities, admission context, required authority/capability/approval metadata, failure envelope and tool-call/capability-invocation identity. Kernel source and default catalogs MUST NOT contain a route selector or conditional branch for Research, AOX, HMMER, Vina, Slurm or another Plugin-specific capability.

#### Scenario: Register a non-biological capability
- **WHEN** an enabled code-review extension supplies a valid unique ToolSpec through composition
- **THEN** the Kernel validates, routes and records its invocation without a Kernel source modification or domain-specific branch

#### Scenario: Unknown tool is requested
- **WHEN** an Agent invokes a dotted name absent from its exact Session tool catalog
- **THEN** the Kernel returns a bounded unknown-tool result and performs no aliasing, fallback or ambient discovery

### Requirement: Finish validation is extension-aware and Kernel-controlled
The Kernel MUST expose a generic finish-validator SPI and MUST invoke only validators pinned to the Session and applicable Task when the Task owner explicitly requests finish. A validator MUST be read-only with respect to Core state and MUST return a closed acceptance or rejection result; it MUST NOT call `task.finish` or convert its own receipt into Task terminal state.

#### Scenario: Science validator rejects incomplete evidence
- **WHEN** a Task owner requests finish and the bound Science validator reports missing exact deliverable evidence
- **THEN** the Kernel leaves the Task non-terminal and returns the validator's typed bounded rejection

#### Scenario: Report is published before finish
- **WHEN** a Reporting extension records a valid report publication but the Task owner has not requested finish
- **THEN** the report remains an extension fact and the Task remains unchanged

### Requirement: Kernel dependency direction is mechanically enforced
`openzyme-kernel` MUST depend only on `openzyme-contracts`, `openzyme-extension-spi` and explicitly approved implementation-free support libraries. It MUST NOT import or declare dependencies on concrete Adapters, Distribution packages, Host/Client/UI, runtime implementations, Research, Reporting, Science, Compute/HPC, EnzymeDesign or `archive/`; temporary migration re-exports MUST be allowlisted, single-directional and deleted before completion.

#### Scenario: Core imports a Research implementation
- **WHEN** AST, import-linter, pyproject or built-wheel inspection finds a Kernel-to-Research import or dependency
- **THEN** the boundary qualification fails even if runtime tests are green

#### Scenario: Temporary legacy import survives final cutover
- **WHEN** a final source or wheel still exposes `openzyme-domain`, the old `openzyme-core`, `openzyme-runtime` or `openzyme-engines` as a second implementation authority
- **THEN** the change remains incomplete until the import and its caller ledger entry are removed
