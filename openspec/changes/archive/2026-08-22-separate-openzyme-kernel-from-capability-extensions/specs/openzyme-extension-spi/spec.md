## ADDED Requirements

### Requirement: Kernel Adapter Plugin Driver and Distribution are distinct contracts
The architecture MUST define Kernel, Adapter, Plugin, Driver and Distribution as separate closed concepts. Kernel MUST own cross-domain canonical rules; an Adapter MUST implement an existing Port without adding top-level semantics; a Plugin MAY add typed state/tools/workers/projections; a Driver MUST remain subordinate to its owning Plugin and translate typed requests to a route; a Distribution MUST only select exact components and MUST NOT own business state.

An Adapter MAY depend on a Plugin distribution only when the dependency exposes the exact public Port contract that the Adapter implements. Such a contract-only dependency MUST be explicitly enumerated by the source-bound architecture policy and MUST NOT expose Plugin application services, repositories, workers, projections or composition internals. The architecture MUST NOT generally permit arbitrary Adapter-to-Plugin dependencies.

#### Scenario: Slurm Adapter implements the HPC scheduler Port

- **WHEN** the Slurm Adapter imports the HPC Plugin's public scheduler request, receipt and Port contracts
- **THEN** the source-bound policy accepts only that explicitly reviewed contract-only dependency
- **AND** rejects imports of HPC Plugin services, repositories, workers or Host composition internals

#### Scenario: Standard is inspected as a layer
- **WHEN** source, manifest or documentation represents OpenZyme Standard as a semantic dependency layer between Kernel and Plugins
- **THEN** architecture qualification fails and identifies Standard as a Distribution composition instead

#### Scenario: Adapter adds a vendor-specific Agent tool
- **WHEN** a concrete SQLite, OpenAI, SSH or Slurm Adapter registers a new Agent-facing semantic tool without an owning Plugin contract
- **THEN** composition rejects the contribution before partial activation

### Requirement: Extension SPI is implementation-free
`openzyme-extension-spi` MUST contain only closed ExtensionManifest, contribution, Driver/Route, qualification, worker, projection and validator protocols and MUST depend only on `openzyme-contracts`. Importing it MUST NOT require Kernel implementation, SQLite, FastAPI, LangChain, Provider SDKs, Git execution, containers, SSH, Slurm or scientific libraries.

#### Scenario: Install the SPI alone
- **WHEN** a fresh environment installs only Contracts and Extension SPI
- **THEN** both import without I/O and a fixture Plugin can construct and validate a complete manifest

#### Scenario: Implementation type crosses the SPI
- **WHEN** an SPI annotation or serialized descriptor references a concrete repository, FastAPI route object, LangChain message, SSH client or scientific implementation class
- **THEN** contract and wheel qualification fail

### Requirement: Plugins use narrow Kernel application services
Plugins MUST receive only typed public services such as Task, Protocol, Approval, Authority, Publication, ControlledOperation, Continuation, Failure, CapabilityQuery, ExtensionInvocation and TaskEvidence services. A Plugin MUST NOT receive `CoreRepositories`, a raw store connection, Host internal service, Git storage locator or unrestricted mutation callback.

#### Scenario: Plugin requests a Core mutation
- **WHEN** a Plugin needs to attach evidence or send a handoff
- **THEN** it submits the corresponding typed Kernel command under the exact Session/Agent/authority/fence context

#### Scenario: Plugin obtains repository authority
- **WHEN** activation attempts to inject Core repositories or a raw SQLite connection into a Plugin runtime
- **THEN** activation fails before any route, worker or writer starts

### Requirement: Plugin contributions are typed and closed
The SPI MUST expose separate contributions for manifest identity, tools, provided and required capabilities, qualification specs, routes, projections, workers, Task evidence validators, extension schemas and transaction participants. It MUST NOT expose an `on_any_event` or equivalent hook that can observe and mutate arbitrary Core state.

#### Scenario: Register a tool contribution
- **WHEN** a Plugin supplies a ToolContribution
- **THEN** composition validates its exact owner, schema, governance, capability requirements and digest before adding it to the declared catalog

#### Scenario: Plugin registers an arbitrary event hook
- **WHEN** a manifest declares an unbounded callback over all Kernel events or tables
- **THEN** closed-schema validation rejects the manifest

### Requirement: Drivers remain subordinate to Plugins
A Driver MAY be packaged separately, but MUST declare its owning Plugin contract, supported route kind, required Adapter Ports and exact driver digest. It MUST NOT activate independently, own a top-level tool/state namespace or replace another Driver after Session pinning.

#### Scenario: Select an HPC HMMER Driver
- **WHEN** EnzymeDesign composition selects a Driver for an HMMER route
- **THEN** the Driver contributes only workload compilation/result parsing under the exact HMMER Plugin and route identities

#### Scenario: Installed Driver self-activates
- **WHEN** an installed Driver entry point is absent from the owning Plugin and Distribution manifests
- **THEN** it contributes no route, tool, worker or effect

### Requirement: SPI and documentation move together
The Contracts/SPI README, main architecture, `docs/v3/` capability/runtime documents, Plugin authoring guide and executable import/manifest tests MUST describe the same public services, contribution types, dependency direction and forbidden authorities.

#### Scenario: Documentation exposes a removed broad hook
- **WHEN** current documentation tells Plugin authors to import Host internals, CoreRepositories or an unrestricted event hook
- **THEN** source-to-document qualification fails
