## ADDED Requirements

### Requirement: OpenZyme Standard is an explicit official Distribution
`openzyme-standard` MUST be a versioned Distribution rather than a semantic dependency layer. It MUST select Kernel, one exact ControlStorePort Adapter, one exact Git/LFS WorkspaceBackendPort Adapter, generic Host API, HTTP client/CLI, Core UI, one AgentTurnPort Adapter and one ProcessIsolationPort Adapter. Its required semantic Plugin set MUST be empty. The Distribution MUST be data-driven and digest-bound and MUST NOT hardcode Research, Reporting, Science, Compute/HPC or EnzymeDesign capabilities.

#### Scenario: Start the Standard composition
- **WHEN** a deployment supplies the exact Standard Distribution manifest and all required Adapter packages
- **THEN** the Host verifies and activates one closed Standard bundle before enabling writers or routes

#### Scenario: Vertical package is absent
- **WHEN** no EnzymeDesign or general extension wheel is installed
- **THEN** Standard still starts and no missing vertical import or fallback registration occurs

### Requirement: Plugin-free Standard remains productively usable
With no semantic Plugin activated, Standard MUST support Session creation, Task/dependency, Agent/delegation/inbox/protocol, Approval, AgentAuthorityLease, runtime command lifecycle, structured local workspace observation/mutation/process operation and the base repository/checkpoint/publication/handoff semantics. Missing Plugin capabilities MUST be absent rather than represented by broken Kernel fields.

#### Scenario: Run a Plugin-free collaboration
- **WHEN** an operator creates a Session, delegates a Task, drains a fake/default bounded runtime turn and publishes a file revision under Standard with no extensions
- **THEN** each Core fact follows its normal state machine and the `extensions` projection contains no fabricated domain section

#### Scenario: Request an absent extension tool
- **WHEN** an Agent requests `deep_research.start` in Plugin-free Standard
- **THEN** the exact Session catalog returns unknown-tool with no implicit installation, alias or Host special case

### Requirement: SQLite is the Standard persistence adapter
`openzyme-store-sqlite` MUST implement Kernel repository ports, schema bootstrap, migration verification, short Unit of Work and extension state participation without being imported by Contracts or Kernel. Startup MUST verify exact schema/composition proof read-only before opening writers.

#### Scenario: Restart Standard on current state
- **WHEN** the Standard Host restarts with the same verified database and composition bundle
- **THEN** canonical Core identities, leases/fences, commands, operations and Session pins are restored through repository ports without process-local shadow truth

#### Scenario: Schema owner manifest is inconsistent
- **WHEN** one table is unowned, multiply owned or its migration digest differs from the active bundle
- **THEN** startup fails before mutation and does not run an opportunistic migration or compatibility reader

### Requirement: Git and Git LFS mechanisms are Standard Adapters
`openzyme-workspace-git-lfs` MUST implement repository provisioning, private workspace, checkpoint/publication transport, Git credentials, refs/hooks, bare storage, Git LFS byte closure/pin/GC and compute-tree preparation behind Kernel workspace Ports. It MUST preserve the exact commit/tree/ref/LFS identities required by the Git-shaped Kernel contract.

#### Scenario: Verify a publication through local Git/LFS
- **WHEN** the adapter observes a clean commit/tree and complete actual LFS bytes for an authorized publication intent
- **THEN** it returns the exact verification receipt needed by Kernel without exposing credential, bare-root or object-store locators

#### Scenario: LFS bytes are missing
- **WHEN** pointer metadata exists but an exact LFS object's bytes or size cannot be verified
- **THEN** publication/execution admission fails with no hidden fetch from an undeclared source and no PublishedRevision is recorded

### Requirement: Generic Host mounts only declared extension surfaces
`openzyme-host-api` MUST be a generic composition root that owns security, Core routes, activation, public contract negotiation and extension mounting. It MUST NOT import AOX, HMMER, scientific finalizers, concrete Research engines, HPC/Slurm implementations or runner services unless they are supplied through a declared extension/composition port.

#### Scenario: Build the generic Host wheel
- **WHEN** the Host wheel is built and inspected without optional extension distributions
- **THEN** its metadata and contents contain no vertical implementation and every Core route remains available

#### Scenario: Mount a declared route provider
- **WHEN** an enabled extension passes manifest and route-collision validation
- **THEN** Host mounts exactly its declared handlers under their contract identity and records them in the projection/release catalog

### Requirement: CLI and Core UI are thin contract clients
`openzyme-host-cli` MUST depend on `openzyme-client` and Contracts rather than runtime or repository implementations. The Core Web UI MUST consume only the `@2` Core schema plus manifest-declared extension renderers, and MUST block mutation on contract, bundle or renderer mismatch.

#### Scenario: Run CLI without runtime implementation imports
- **WHEN** the CLI displays a Session, Task or runtime command result
- **THEN** it uses the HTTP client DTOs and does not construct a LangChain/provider/runtime implementation object

#### Scenario: UI lacks an extension renderer
- **WHEN** a Session includes an extension projection whose required renderer is absent or digest-mismatched
- **THEN** the UI reports the exact incompatible extension and disables affected mutation controls without interpreting it as Core data

### Requirement: Standard defaults are explicit and replaceable
Default runtime, process, store and workspace adapters MUST be selected by the Standard composition manifest and MUST have versioned implementation identities. Environment variables or import availability MUST NOT silently replace the selected adapter, add capabilities or change a Session bundle.

#### Scenario: Another Provider credential is present
- **WHEN** the environment contains credentials for a Provider not selected by composition
- **THEN** Standard does not instantiate or expose that Provider

#### Scenario: Selected process adapter is unavailable
- **WHEN** a required process adapter cannot satisfy its startup preflight
- **THEN** activation fails with a typed adapter-preflight error rather than falling back to Host subprocess execution

### Requirement: Standard selects one exact implementation per single-valued Adapter slot
The Standard Distribution MUST bind exactly one implementation identity for each required single-valued Port, including control store, workspace backend, Agent turn and process isolation. Missing or ambiguous providers MUST make the deployment not ready; credentials, import order or environment variables MUST NOT resolve ambiguity.

#### Scenario: Two stores claim the selected slot
- **WHEN** both SQLite and PostgreSQL are present but the Distribution does not select exactly one ControlStorePort provider
- **THEN** activation fails before either opens a writer

#### Scenario: Podman is explicitly selected
- **WHEN** `openzyme-process-podman` is selected and passes preflight
- **THEN** local process execution binds its exact implementation identity and no native-subprocess fallback is eligible

### Requirement: Standard installation closure excludes optional capabilities
Installing the Standard distribution without extras MUST NOT install Tavily, Biopython, NumPy, RDKit, Meeko, SSH/Slurm or EnzymeDesign packages. Wheel metadata/content qualification MUST prove that optional extension dependencies enter only through explicitly selected distributions.

#### Scenario: Inspect a fresh Standard environment
- **WHEN** built Standard wheels are installed into an empty environment with no extension extras
- **THEN** package metadata and import inventory contain only Kernel, Standard adapters and their approved implementation dependencies

#### Scenario: Optional dependency leaks into Standard
- **WHEN** a vertical or general-extension-only package appears in the default Standard dependency closure
- **THEN** layered qualification fails regardless of whether the package is imported at runtime

### Requirement: Standard implementation and documentation move together
Each Standard adapter, route, client, configuration or deployment change MUST update the corresponding main architecture, `docs/v3/`, package/app README and operator documentation in the same implementation slice. A stale command, owner statement, package path or fallback description MUST keep that slice incomplete.

#### Scenario: Git implementation moves but documentation does not
- **WHEN** source ownership places Git/LFS in `openzyme-workspace-git-lfs` while current docs still describe Kernel as executing Git commands
- **THEN** source-to-document drift qualification fails and the migration task cannot be marked complete

#### Scenario: Source and docs agree
- **WHEN** current source, manifest, schema, public imports, README commands and stable architecture documents identify the same Standard owners and failure behavior
- **THEN** the documentation alignment gate records source-bound evidence for that slice
